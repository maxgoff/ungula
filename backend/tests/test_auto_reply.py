"""
Tests for the auto_reply module: directives, chunker, and dispatcher.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ungula.auto_reply.chunker import CHANNEL_LIMITS, chunk_response
from ungula.auto_reply.directives import (
    KNOWN_DIRECTIVES,
    Directive,
    DirectiveParser,
    parse_directive,
)
from ungula.auto_reply.dispatch import AutoReplyDispatcher


# ---------------------------------------------------------------------------
# parse_directive() tests
# ---------------------------------------------------------------------------

class TestParseDirective:
    """Tests for the module-level parse_directive function."""

    # -- known directives ---------------------------------------------------

    @pytest.mark.parametrize("command", sorted(KNOWN_DIRECTIVES))
    def test_known_directives_recognized(self, command: str):
        """Every known directive should be parsed successfully."""
        result = parse_directive(f"/{command}")
        assert result is not None
        assert result.command == command
        assert result.args == ""

    def test_model_with_args(self):
        """parse_directive should capture everything after the command as args."""
        result = parse_directive("/model gpt-4-turbo")
        assert result is not None
        assert result.command == "model"
        assert result.args == "gpt-4-turbo"

    def test_model_with_multiword_args(self):
        """Args should capture multiple words."""
        result = parse_directive("/model claude-3 opus")
        assert result is not None
        assert result.args == "claude-3 opus"

    def test_directive_preserves_original(self):
        """The original field should contain the full original text."""
        text = "/status please"
        result = parse_directive(text)
        assert result is not None
        assert result.original == text

    # -- non-directives / edge cases ----------------------------------------

    def test_plain_text_returns_none(self):
        """Regular text should not be interpreted as a directive."""
        assert parse_directive("hello world") is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        assert parse_directive("") is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only string should return None."""
        assert parse_directive("   ") is None

    def test_unknown_command_returns_none(self):
        """A slash-command that is not in KNOWN_DIRECTIVES should return None."""
        assert parse_directive("/foobar") is None

    def test_slash_alone_returns_none(self):
        """A lone slash should return None (no word characters follow)."""
        assert parse_directive("/") is None

    def test_slash_with_special_chars_returns_none(self):
        """Slash followed by non-word characters should return None."""
        assert parse_directive("/!!!") is None

    def test_leading_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped before parsing."""
        result = parse_directive("  /ping  ")
        assert result is not None
        assert result.command == "ping"

    def test_case_insensitive(self):
        """Directives should be case-insensitive."""
        result = parse_directive("/HELP")
        assert result is not None
        assert result.command == "help"

    def test_mixed_case(self):
        """Mixed-case directives should be lowered."""
        result = parse_directive("/StAtUs")
        assert result is not None
        assert result.command == "status"

    def test_multiline_args(self):
        """Args spanning multiple lines should be captured (re.DOTALL)."""
        text = "/model line1\nline2\nline3"
        result = parse_directive(text)
        assert result is not None
        assert "line2" in result.args
        assert "line3" in result.args

    def test_directive_mid_sentence_not_parsed(self):
        """Text that does not START with a slash should not parse."""
        assert parse_directive("Please /help me") is None

    def test_all_known_directives_present(self):
        """Verify the known directive set matches what we expect."""
        expected = {"model", "think", "status", "compact", "reset", "help", "ping"}
        assert KNOWN_DIRECTIVES == expected


# ---------------------------------------------------------------------------
# DirectiveParser tests
# ---------------------------------------------------------------------------

class TestDirectiveParser:
    """Tests for the configurable DirectiveParser class."""

    def test_default_parser_recognizes_known(self):
        """Default parser should recognize all KNOWN_DIRECTIVES."""
        parser = DirectiveParser()
        for cmd in KNOWN_DIRECTIVES:
            result = parser.parse(f"/{cmd}")
            assert result is not None
            assert result.command == cmd

    def test_default_parser_rejects_unknown(self):
        """Default parser should reject unknown commands."""
        parser = DirectiveParser()
        assert parser.parse("/admin") is None

    def test_extra_directives(self):
        """Extra directives should be recognized."""
        parser = DirectiveParser(extra_directives={"admin", "debug"})
        assert parser.parse("/admin") is not None
        assert parser.parse("/debug") is not None
        # Original directives still work
        assert parser.parse("/help") is not None

    def test_aliases(self):
        """Aliases should resolve to their target directive."""
        parser = DirectiveParser(aliases={"h": "help", "s": "status"})
        result = parser.parse("/h")
        assert result is not None
        assert result.command == "help"

        result = parser.parse("/s")
        assert result is not None
        assert result.command == "status"

    def test_alias_with_args(self):
        """Alias should resolve and args should be preserved."""
        parser = DirectiveParser(aliases={"m": "model"})
        result = parser.parse("/m gpt-4")
        assert result is not None
        assert result.command == "model"
        assert result.args == "gpt-4"

    def test_alias_to_unknown_rejected(self):
        """An alias pointing to a command not in the directive set should be rejected."""
        parser = DirectiveParser(aliases={"x": "nonexistent"})
        assert parser.parse("/x") is None

    def test_alias_overrides_case(self):
        """Alias resolution should be case-insensitive on the input side."""
        parser = DirectiveParser(aliases={"H": "help"})
        # Input is lowered, so /H becomes "h", which won't match alias key "H"
        # unless the alias dict is also lowercase. Let's verify actual behavior.
        result = parser.parse("/H")
        # "H" lowered is "h", alias dict has key "H" not "h", so no match.
        # "h" is not in KNOWN_DIRECTIVES, so it returns None.
        # This verifies alias keys should be lowercase for consistency.
        assert result is None

    def test_alias_lowercase_key(self):
        """Alias keys should be lowercase to match lowered command."""
        parser = DirectiveParser(aliases={"h": "help"})
        result = parser.parse("/H")
        assert result is not None
        assert result.command == "help"

    def test_empty_string(self):
        """Parser should handle empty strings gracefully."""
        parser = DirectiveParser()
        assert parser.parse("") is None

    def test_no_slash_prefix(self):
        """Parser should return None when no slash prefix."""
        parser = DirectiveParser()
        assert parser.parse("help") is None

    def test_original_preserved(self):
        """The original text should be preserved in the Directive."""
        parser = DirectiveParser()
        text = "  /ping  "
        result = parser.parse(text)
        assert result is not None
        assert result.original == text.strip()

    def test_extra_directives_do_not_mutate_known(self):
        """Creating a parser with extras should not mutate KNOWN_DIRECTIVES."""
        original = KNOWN_DIRECTIVES.copy()
        DirectiveParser(extra_directives={"custom_cmd"})
        assert KNOWN_DIRECTIVES == original


# ---------------------------------------------------------------------------
# chunk_response() tests
# ---------------------------------------------------------------------------

class TestChunkResponse:
    """Tests for the response chunker."""

    def test_short_text_no_chunking(self):
        """Text within the limit should come back as a single chunk."""
        text = "Hello, world!"
        chunks = chunk_response(text)
        assert chunks == [text]

    def test_short_text_all_channels(self):
        """Short text should not be chunked on any channel."""
        text = "Short message."
        for channel in CHANNEL_LIMITS:
            chunks = chunk_response(text, channel=channel)
            assert len(chunks) == 1
            assert chunks[0] == text

    def test_empty_string(self):
        """Empty string should return a single empty-ish chunk or empty list."""
        chunks = chunk_response("")
        # Empty string is <= limit, so returns [""]
        assert chunks == [""]

    # -- channel-specific limits --------------------------------------------

    def test_discord_limit(self):
        """Discord has a 2000-char limit."""
        assert CHANNEL_LIMITS["discord"] == 2000
        text = "A" * 3000
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_slack_limit(self):
        """Slack has a 4000-char limit."""
        assert CHANNEL_LIMITS["slack"] == 4000
        text = "B" * 6000
        chunks = chunk_response(text, channel="slack")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 4000

    def test_telegram_limit(self):
        """Telegram has a 4096-char limit."""
        assert CHANNEL_LIMITS["telegram"] == 4096
        text = "C" * 8000
        chunks = chunk_response(text, channel="telegram")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_signal_limit(self):
        """Signal has a 10000-char limit."""
        assert CHANNEL_LIMITS["signal"] == 10000

    def test_imessage_limit(self):
        """iMessage has a 10000-char limit."""
        assert CHANNEL_LIMITS["imessage"] == 10000

    def test_default_limit_used_for_unknown_channel(self):
        """Unknown channels should use the default limit."""
        text = "D" * 3000
        chunks = chunk_response(text, channel="unknown_channel")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= CHANNEL_LIMITS["default"]

    def test_custom_max_length_overrides_channel(self):
        """An explicit max_length should override the channel's limit."""
        text = "E" * 500
        chunks = chunk_response(text, channel="discord", max_length=100)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 100

    # -- paragraph boundary splitting ---------------------------------------

    def test_split_at_paragraph_boundary(self):
        """Chunker should prefer splitting at paragraph boundaries."""
        para1 = "A" * 1200
        para2 = "B" * 1200
        text = f"{para1}\n\n{para2}"
        # Total is ~2402 chars, exceeding the discord 2000-char limit.
        # Each individual paragraph fits in one chunk, so the chunker
        # should split cleanly at the paragraph break.
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) == 2
        assert "A" in chunks[0]
        assert "B" in chunks[1]

    def test_multiple_paragraphs(self):
        """Multiple paragraphs should be split cleanly."""
        paragraphs = ["Paragraph " + str(i) + ". " + "x" * 800 for i in range(5)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_response(text, channel="discord")
        # Should produce multiple chunks, all within limit
        for chunk in chunks:
            assert len(chunk) <= 2000

    # -- sentence boundary splitting ----------------------------------------

    def test_split_at_sentence_boundary(self):
        """When no paragraph break exists, should split at sentence boundary."""
        # One giant paragraph with sentences
        sentences = ["This is sentence number " + str(i) + "." for i in range(100)]
        text = " ".join(sentences)
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    # -- word boundary splitting --------------------------------------------

    def test_split_at_word_boundary(self):
        """When no sentence breaks, should split at word boundaries."""
        # Words without periods
        words = ["word" for _ in range(600)]
        text = " ".join(words)  # 600 * 5 - 1 = 2999 chars
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    # -- hard cut fallback --------------------------------------------------

    def test_hard_cut_no_spaces(self):
        """A solid block with no break points should be hard-cut at limit."""
        text = "A" * 5000
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) >= 3
        for chunk in chunks:
            assert len(chunk) <= 2000

    # -- all content preserved ----------------------------------------------

    def test_all_content_preserved(self):
        """Chunking should not lose content (modulo whitespace trimming)."""
        para1 = "First paragraph content here."
        para2 = "Second paragraph content here."
        para3 = "Third paragraph content here."
        text = f"{para1}\n\n{para2}\n\n{para3}"
        chunks = chunk_response(text, max_length=50)
        rejoined = " ".join(chunks)
        assert "First paragraph" in rejoined
        assert "Second paragraph" in rejoined
        assert "Third paragraph" in rejoined

    def test_no_empty_chunks(self):
        """Chunker should not produce empty chunks."""
        text = "Hello\n\n\n\nWorld\n\n\n\nFoo"
        chunks = chunk_response(text, max_length=10)
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_exactly_at_limit(self):
        """Text exactly at the limit should be a single chunk."""
        text = "X" * 2000
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_one_over_limit(self):
        """Text one char over the limit should split."""
        text = "X" * 2001
        chunks = chunk_response(text, channel="discord")
        assert len(chunks) == 2


# ---------------------------------------------------------------------------
# AutoReplyDispatcher tests
# ---------------------------------------------------------------------------

class TestAutoReplyDispatcher:
    """Tests for the AutoReplyDispatcher."""

    # -- directive dispatch -------------------------------------------------

    async def test_dispatch_help(self):
        """The /help directive should return a help message."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/help")
        assert result is not None
        assert len(result) >= 1
        assert "Available commands" in result[0]

    async def test_dispatch_ping(self):
        """The /ping directive should return a pong response."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/ping")
        assert result is not None
        assert "Pong" in result[0]

    async def test_dispatch_status_no_context(self):
        """The /status directive without context should return basic status."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/status")
        assert result is not None
        assert "System Status" in result[0]

    async def test_dispatch_status_with_agent_runner(self):
        """The /status directive with agent_runner context should include provider info."""
        mock_runner = MagicMock()
        mock_runner.registry.list_providers.return_value = ["openai", "anthropic"]
        mock_runner.default_provider = "openai"
        mock_runner.tool_registry = None

        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch(
            "/status",
            context={"agent_runner": mock_runner},
        )
        assert result is not None
        combined = " ".join(result)
        assert "openai" in combined
        assert "anthropic" in combined

    async def test_dispatch_status_with_tools(self):
        """The /status directive should list tools when tool_registry is present."""
        mock_runner = MagicMock()
        mock_runner.registry.list_providers.return_value = ["openai"]
        mock_runner.default_provider = "openai"
        mock_runner.tool_registry.list_tools.return_value = ["shell", "web_search"]

        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch(
            "/status",
            context={"agent_runner": mock_runner},
        )
        assert result is not None
        combined = " ".join(result)
        assert "shell" in combined
        assert "web_search" in combined

    async def test_dispatch_model_no_args(self):
        """The /model directive with no args should show current model."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/model")
        assert result is not None
        assert "Current model" in result[0] or "Usage" in result[0]

    async def test_dispatch_model_with_args(self):
        """The /model directive with args should acknowledge the switch."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/model gpt-4-turbo")
        assert result is not None
        assert "gpt-4-turbo" in result[0]

    async def test_dispatch_think(self):
        """The /think directive should acknowledge thinking mode."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/think")
        assert result is not None
        assert "Thinking" in result[0] or "reasoning" in result[0]

    async def test_dispatch_compact(self):
        """The /compact directive should acknowledge compaction."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/compact")
        assert result is not None
        assert "compaction" in result[0].lower() or "compact" in result[0].lower()

    async def test_dispatch_reset(self):
        """The /reset directive should acknowledge the reset."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/reset")
        assert result is not None
        assert "reset" in result[0].lower()

    # -- non-directive passthrough ------------------------------------------

    async def test_normal_message_returns_none(self):
        """Normal messages should return None (not handled as directives)."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("Hello, how are you?")
        assert result is None

    async def test_unknown_directive_returns_message(self):
        """An unknown directive (added via parser) should return a fallback."""
        parser = DirectiveParser(extra_directives={"custom"})
        dispatcher = AutoReplyDispatcher(parser=parser)
        result = await dispatcher.try_dispatch("/custom")
        assert result is not None
        # The dispatcher has no _handle_custom, so it falls back to "Unknown directive"
        assert "Unknown directive" in result[0]

    # -- channel-aware chunking ---------------------------------------------

    async def test_dispatch_respects_channel_chunking(self):
        """Dispatcher should chunk responses for the given channel."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/help", channel="discord")
        assert result is not None
        for chunk in result:
            assert len(chunk) <= 2000

    async def test_dispatch_with_custom_parser(self):
        """Dispatcher should use the provided custom parser."""
        parser = DirectiveParser(aliases={"p": "ping"})
        dispatcher = AutoReplyDispatcher(parser=parser)
        result = await dispatcher.try_dispatch("/p")
        assert result is not None
        assert "Pong" in result[0]

    # -- edge cases ---------------------------------------------------------

    async def test_dispatch_empty_string(self):
        """Empty string should not be treated as a directive."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("")
        assert result is None

    async def test_dispatch_slash_only(self):
        """A lone slash should not be treated as a directive."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/")
        assert result is None

    async def test_dispatch_with_leading_whitespace(self):
        """Directives with leading whitespace should still parse."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("  /ping  ")
        assert result is not None
        assert "Pong" in result[0]

    async def test_dispatch_context_defaults_to_empty_dict(self):
        """When context is None, handler should receive an empty dict."""
        dispatcher = AutoReplyDispatcher()
        # /status accesses context.get("agent_runner") -- should not crash
        result = await dispatcher.try_dispatch("/status", context=None)
        assert result is not None
        assert "System Status" in result[0]

    async def test_dispatch_model_no_args_no_context(self):
        """The /model directive with no args and no agent_runner should show 'unknown'."""
        dispatcher = AutoReplyDispatcher()
        result = await dispatcher.try_dispatch("/model", context={})
        assert result is not None
        assert "unknown" in result[0].lower() or "default" in result[0].lower()
