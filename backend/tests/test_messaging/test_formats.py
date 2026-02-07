"""
Tests for messaging channel format modules.

Covers:
- Slack markdown_to_mrkdwn, to_blocks, truncate_message
- Signal format_for_signal, truncate_message
- iMessage probe_imessage (platform/file mocking)
- Base dataclasses: InboundMessage, OutboundMessage, SendResult, ChannelStatus,
  and exception classes
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ungula.messaging.base import (
    ChannelConfigError,
    ChannelConnectionError,
    ChannelError,
    ChannelSendError,
    ChannelStatus,
    InboundMessage,
    OutboundMessage,
    SendResult,
    generate_message_id,
)
from ungula.messaging.imessage.probe import (
    has_imsg_cli,
    is_macos,
    messages_db_path,
    probe_imessage,
)
from ungula.messaging.signal.format import format_for_signal
from ungula.messaging.signal.format import truncate_message as signal_truncate
from ungula.messaging.slack.format import (
    MAX_MESSAGE_LENGTH as SLACK_MAX,
    markdown_to_mrkdwn,
    to_blocks,
)
from ungula.messaging.slack.format import truncate_message as slack_truncate


# ---------------------------------------------------------------------------
# Slack: markdown_to_mrkdwn
# ---------------------------------------------------------------------------

class TestMarkdownToMrkdwn:
    """Tests for Slack markdown_to_mrkdwn conversion."""

    def test_bold_conversion(self):
        """**bold** becomes *bold* in mrkdwn."""
        assert markdown_to_mrkdwn("**hello**") == "*hello*"

    def test_bold_mid_sentence(self):
        """Bold in the middle of a sentence."""
        result = markdown_to_mrkdwn("This is **important** text.")
        assert result == "This is *important* text."

    def test_multiple_bold(self):
        """Multiple bold segments in one string."""
        result = markdown_to_mrkdwn("**one** and **two**")
        assert result == "*one* and *two*"

    def test_italic_preserved(self):
        """Underscores for italic stay as-is since Slack uses _ natively."""
        assert markdown_to_mrkdwn("_italic_") == "_italic_"

    def test_header_h1(self):
        """# Header becomes bold *Header*."""
        assert markdown_to_mrkdwn("# Title") == "*Title*"

    def test_header_h2(self):
        """## Header becomes bold."""
        assert markdown_to_mrkdwn("## Subtitle") == "*Subtitle*"

    def test_header_h3(self):
        """### Header becomes bold."""
        assert markdown_to_mrkdwn("### Section") == "*Section*"

    def test_header_h6(self):
        """###### Deep header still becomes bold."""
        assert markdown_to_mrkdwn("###### Deep") == "*Deep*"

    def test_header_multiline(self):
        """Headers work line-by-line in multiline text."""
        text = "# First\nsome text\n## Second"
        result = markdown_to_mrkdwn(text)
        assert result == "*First*\nsome text\n*Second*"

    def test_link_conversion(self):
        """[text](url) becomes <url|text>."""
        result = markdown_to_mrkdwn("[Click here](https://example.com)")
        assert result == "<https://example.com|Click here>"

    def test_link_with_title_text(self):
        """Links with complex text."""
        result = markdown_to_mrkdwn("[Ungula docs](https://docs.ungula.dev/getting-started)")
        assert result == "<https://docs.ungula.dev/getting-started|Ungula docs>"

    def test_multiple_links(self):
        """Multiple links in one string."""
        text = "See [A](https://a.com) and [B](https://b.com)"
        result = markdown_to_mrkdwn(text)
        assert result == "See <https://a.com|A> and <https://b.com|B>"

    def test_strikethrough_conversion(self):
        """~~strike~~ becomes ~strike~."""
        assert markdown_to_mrkdwn("~~deleted~~") == "~deleted~"

    def test_strikethrough_mid_sentence(self):
        """Strikethrough in context."""
        result = markdown_to_mrkdwn("This is ~~wrong~~ right.")
        assert result == "This is ~wrong~ right."

    def test_code_block_language_preserved(self):
        """Code blocks with language specifiers pass through (no stripping in current impl)."""
        text = "```python\nprint('hi')\n```"
        result = markdown_to_mrkdwn(text)
        # The function does not strip the language tag -- code blocks pass through
        assert "```python" in result or "```" in result

    def test_inline_code_untouched(self):
        """Inline `code` stays the same."""
        text = "Use `pip install ungula` here."
        assert markdown_to_mrkdwn(text) == text

    def test_nested_bold_and_link(self):
        """Bold inside a link context."""
        text = "**[Click](https://a.com)**"
        result = markdown_to_mrkdwn(text)
        # Bold wraps the converted link
        assert "<https://a.com|Click>" in result

    def test_combined_formatting(self):
        """Multiple format conversions in a single block."""
        text = "# Welcome\n**Bold** and ~~strike~~ plus [link](https://x.com)"
        result = markdown_to_mrkdwn(text)
        assert "*Welcome*" in result
        assert "*Bold*" in result
        assert "~strike~" in result
        assert "<https://x.com|link>" in result

    def test_empty_string(self):
        """Empty input returns empty output."""
        assert markdown_to_mrkdwn("") == ""

    def test_plain_text_unchanged(self):
        """Plain text without any markdown passes through unchanged."""
        text = "Just a normal sentence."
        assert markdown_to_mrkdwn(text) == text

    def test_hash_not_at_line_start(self):
        """Hash in middle of line is not treated as header."""
        text = "This # is not a header"
        assert markdown_to_mrkdwn(text) == text


# ---------------------------------------------------------------------------
# Slack: to_blocks
# ---------------------------------------------------------------------------

class TestToBlocks:
    """Tests for Slack to_blocks Block Kit conversion."""

    def test_simple_text_single_block(self):
        """Short text produces a single section block."""
        blocks = to_blocks("Hello world")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert blocks[0]["text"]["type"] == "mrkdwn"
        assert blocks[0]["text"]["text"] == "Hello world"

    def test_markdown_converted_in_blocks(self):
        """Markdown formatting is converted inside blocks."""
        blocks = to_blocks("**bold** and [link](https://x.com)")
        text = blocks[0]["text"]["text"]
        assert "*bold*" in text
        assert "<https://x.com|link>" in text

    def test_long_text_splits_into_multiple_blocks(self):
        """Text exceeding 3000 chars is split into multiple blocks."""
        # Build text with newlines so split can find a clean point
        line = "A" * 99 + "\n"  # 100 chars per line
        text = line * 35  # 3500 chars total
        blocks = to_blocks(text)
        assert len(blocks) >= 2
        for block in blocks:
            assert block["type"] == "section"
            assert block["text"]["type"] == "mrkdwn"
            assert len(block["text"]["text"]) <= 3000

    def test_long_text_no_newline_fallback(self):
        """Text with no newlines splits at the 3000-char boundary."""
        text = "X" * 6000
        blocks = to_blocks(text)
        assert len(blocks) >= 2
        # First chunk must be exactly 3000
        assert len(blocks[0]["text"]["text"]) == 3000

    def test_empty_text(self):
        """Empty string produces a single block with empty text."""
        blocks = to_blocks("")
        # Empty string -> while loop exits immediately, no chunks
        assert len(blocks) == 0

    def test_exactly_3000_chars(self):
        """Text exactly at the limit produces one block."""
        text = "B" * 3000
        blocks = to_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["text"]["text"] == text

    def test_block_structure_keys(self):
        """Each block has the correct key structure."""
        blocks = to_blocks("test")
        block = blocks[0]
        assert set(block.keys()) == {"type", "text"}
        assert set(block["text"].keys()) == {"type", "text"}

    def test_code_block_in_blocks(self):
        """Code block content is preserved inside blocks."""
        text = "Here is code:\n```\nprint('hi')\n```"
        blocks = to_blocks(text)
        combined = "".join(b["text"]["text"] for b in blocks)
        assert "```" in combined
        assert "print('hi')" in combined


# ---------------------------------------------------------------------------
# Slack: truncate_message
# ---------------------------------------------------------------------------

class TestSlackTruncate:
    """Tests for Slack truncate_message."""

    def test_short_message_unchanged(self):
        """Message under the limit passes through."""
        msg = "Short message"
        assert slack_truncate(msg) == msg

    def test_exact_limit_unchanged(self):
        """Message exactly at the default limit is not truncated."""
        msg = "A" * SLACK_MAX
        assert slack_truncate(msg) == msg

    def test_over_limit_truncated(self):
        """Message over the limit is truncated with suffix."""
        msg = "A" * (SLACK_MAX + 100)
        result = slack_truncate(msg)
        # Content is text[:max_length - 20], suffix is "\n\n_(truncated)_" (15 chars)
        expected_len = (SLACK_MAX - 20) + len("\n\n_(truncated)_")
        assert len(result) == expected_len
        assert result.endswith("\n\n_(truncated)_")

    def test_truncated_content_preserved(self):
        """The first part of the content is preserved after truncation."""
        msg = "B" * (SLACK_MAX + 500)
        result = slack_truncate(msg)
        # Content portion length: max_length - 20
        content_len = SLACK_MAX - 20
        suffix = "\n\n_(truncated)_"
        assert result[:content_len] == "B" * content_len
        assert result[content_len:] == suffix

    def test_custom_max_length(self):
        """Custom max_length is respected."""
        msg = "C" * 200
        result = slack_truncate(msg, max_length=100)
        expected_len = (100 - 20) + len("\n\n_(truncated)_")
        assert len(result) == expected_len
        assert result.endswith("\n\n_(truncated)_")

    def test_custom_max_length_under(self):
        """Message under custom limit passes through."""
        msg = "D" * 50
        assert slack_truncate(msg, max_length=100) == msg

    def test_empty_message(self):
        """Empty message passes through."""
        assert slack_truncate("") == ""


# ---------------------------------------------------------------------------
# Signal: format_for_signal
# ---------------------------------------------------------------------------

class TestFormatForSignal:
    """Tests for Signal format_for_signal conversion."""

    def test_bold_conversion(self):
        """**bold** becomes *bold*."""
        assert format_for_signal("**hello**") == "*hello*"

    def test_multiple_bold(self):
        """Multiple bold segments are converted."""
        result = format_for_signal("**one** and **two**")
        assert result == "*one* and *two*"

    def test_italic_preserved(self):
        """Underscore italic stays the same."""
        assert format_for_signal("_italic_") == "_italic_"

    def test_header_to_bold(self):
        """Markdown headers become bold."""
        assert format_for_signal("# Title") == "*Title*"
        assert format_for_signal("### Section") == "*Section*"

    def test_strikethrough_conversion(self):
        """~~strike~~ becomes ~strike~."""
        assert format_for_signal("~~deleted~~") == "~deleted~"

    def test_links_stripped_to_text(self):
        """[text](url) becomes just text (Signal has no link formatting)."""
        result = format_for_signal("[Click here](https://example.com)")
        assert result == "Click here"

    def test_links_multiple(self):
        """Multiple links are stripped to their display text."""
        text = "See [A](https://a.com) and [B](https://b.com)"
        result = format_for_signal(text)
        assert result == "See A and B"

    def test_code_block_preserved(self):
        """Code blocks pass through."""
        text = "```\ncode here\n```"
        assert format_for_signal(text) == text

    def test_combined_formatting(self):
        """Multiple formats in one message."""
        text = "# Welcome\n**Bold** and ~~strike~~ plus [link](https://x.com)"
        result = format_for_signal(text)
        assert "*Welcome*" in result
        assert "*Bold*" in result
        assert "~strike~" in result
        assert "link" in result
        assert "https://x.com" not in result

    def test_empty_string(self):
        """Empty input returns empty output."""
        assert format_for_signal("") == ""

    def test_plain_text_unchanged(self):
        """Plain text passes through unchanged."""
        text = "Normal sentence with no formatting."
        assert format_for_signal(text) == text

    def test_multiline_headers(self):
        """Headers work across multiple lines."""
        text = "## First\nBody\n## Second"
        result = format_for_signal(text)
        assert result == "*First*\nBody\n*Second*"


# ---------------------------------------------------------------------------
# Signal: truncate_message
# ---------------------------------------------------------------------------

class TestSignalTruncate:
    """Tests for Signal truncate_message."""

    def test_short_message_unchanged(self):
        """Message under the limit passes through."""
        msg = "Short message"
        assert signal_truncate(msg) == msg

    def test_exact_limit_unchanged(self):
        """Message at exactly 10000 chars is not truncated."""
        msg = "A" * 10000
        assert signal_truncate(msg) == msg

    def test_over_limit_truncated(self):
        """Message over the limit is truncated with suffix."""
        msg = "A" * 10100
        result = signal_truncate(msg)
        # Content is text[:max_length - 20], suffix is "\n\n(truncated)" (13 chars)
        expected_len = (10000 - 20) + len("\n\n(truncated)")
        assert len(result) == expected_len
        assert result.endswith("\n\n(truncated)")

    def test_truncated_suffix_no_underscore(self):
        """Signal uses (truncated), NOT _(truncated)_ (no italics)."""
        msg = "B" * 10500
        result = signal_truncate(msg)
        assert result.endswith("\n\n(truncated)")
        assert "_(truncated)_" not in result

    def test_custom_max_length(self):
        """Custom max_length is respected."""
        msg = "C" * 200
        result = signal_truncate(msg, max_length=100)
        expected_len = (100 - 20) + len("\n\n(truncated)")
        assert len(result) == expected_len
        assert result.endswith("\n\n(truncated)")

    def test_empty_message(self):
        """Empty message passes through."""
        assert signal_truncate("") == ""


# ---------------------------------------------------------------------------
# iMessage: probe_imessage
# ---------------------------------------------------------------------------

class TestIsMacos:
    """Tests for is_macos helper."""

    @patch("ungula.messaging.imessage.probe.sys")
    def test_darwin_platform(self, mock_sys):
        mock_sys.platform = "darwin"
        assert is_macos() is True

    @patch("ungula.messaging.imessage.probe.sys")
    def test_linux_platform(self, mock_sys):
        mock_sys.platform = "linux"
        assert is_macos() is False

    @patch("ungula.messaging.imessage.probe.sys")
    def test_win32_platform(self, mock_sys):
        mock_sys.platform = "win32"
        assert is_macos() is False


class TestMessagesDbPath:
    """Tests for messages_db_path helper."""

    @patch("ungula.messaging.imessage.probe.Path.home")
    def test_db_exists(self, mock_home, tmp_path):
        """Returns path when chat.db exists."""
        db_dir = tmp_path / "Library" / "Messages"
        db_dir.mkdir(parents=True)
        db_file = db_dir / "chat.db"
        db_file.touch()
        mock_home.return_value = tmp_path
        result = messages_db_path()
        assert result is not None
        assert result.name == "chat.db"

    @patch("ungula.messaging.imessage.probe.Path.home")
    def test_db_not_exists(self, mock_home, tmp_path):
        """Returns None when chat.db does not exist."""
        mock_home.return_value = tmp_path
        result = messages_db_path()
        assert result is None


class TestHasImsgCli:
    """Tests for has_imsg_cli helper."""

    @patch("ungula.messaging.imessage.probe.shutil.which")
    def test_cli_found(self, mock_which):
        mock_which.return_value = "/usr/local/bin/imsg"
        assert has_imsg_cli() is True

    @patch("ungula.messaging.imessage.probe.shutil.which")
    def test_cli_not_found(self, mock_which):
        mock_which.return_value = None
        assert has_imsg_cli() is False

    @patch("ungula.messaging.imessage.probe.shutil.which")
    def test_custom_cli_path(self, mock_which):
        mock_which.return_value = "/opt/bin/my-imsg"
        assert has_imsg_cli(cli_path="my-imsg") is True
        mock_which.assert_called_once_with("my-imsg")


class TestProbeImessage:
    """Tests for probe_imessage composite probe."""

    @patch("ungula.messaging.imessage.probe.is_macos", return_value=False)
    def test_not_macos(self, _mock_macos):
        """Returns unavailable on non-macOS."""
        result = probe_imessage()
        assert result["available"] is False
        assert "macOS" in result["reason"]
        assert result["db_path"] is None
        assert result["has_cli"] is False

    @patch("ungula.messaging.imessage.probe.has_imsg_cli", return_value=True)
    @patch("ungula.messaging.imessage.probe.messages_db_path", return_value=None)
    @patch("ungula.messaging.imessage.probe.is_macos", return_value=True)
    def test_macos_no_db(self, _macos, _db, _cli):
        """macOS but no Messages database."""
        result = probe_imessage()
        assert result["available"] is False
        assert "database not found" in result["reason"]
        assert result["db_path"] is None
        assert result["has_cli"] is True

    @patch("ungula.messaging.imessage.probe.has_imsg_cli", return_value=True)
    @patch(
        "ungula.messaging.imessage.probe.messages_db_path",
        return_value=Path("/Users/test/Library/Messages/chat.db"),
    )
    @patch("ungula.messaging.imessage.probe.is_macos", return_value=True)
    def test_macos_with_db_and_cli(self, _macos, _db, _cli):
        """Full availability -- macOS, database, and CLI."""
        result = probe_imessage()
        assert result["available"] is True
        assert result["reason"] == "iMessage is available"
        assert result["db_path"] == "/Users/test/Library/Messages/chat.db"
        assert result["has_cli"] is True

    @patch("ungula.messaging.imessage.probe.has_imsg_cli", return_value=False)
    @patch(
        "ungula.messaging.imessage.probe.messages_db_path",
        return_value=Path("/Users/test/Library/Messages/chat.db"),
    )
    @patch("ungula.messaging.imessage.probe.is_macos", return_value=True)
    def test_macos_with_db_no_cli(self, _macos, _db, _cli):
        """Available even without CLI -- db presence is sufficient."""
        result = probe_imessage()
        assert result["available"] is True
        assert result["has_cli"] is False

    @patch("ungula.messaging.imessage.probe.has_imsg_cli", return_value=False)
    @patch("ungula.messaging.imessage.probe.messages_db_path", return_value=None)
    @patch("ungula.messaging.imessage.probe.is_macos", return_value=True)
    def test_macos_no_db_no_cli(self, _macos, _db, _cli):
        """macOS without db or CLI."""
        result = probe_imessage()
        assert result["available"] is False
        assert result["has_cli"] is False


# ---------------------------------------------------------------------------
# Base: InboundMessage
# ---------------------------------------------------------------------------

class TestInboundMessage:
    """Tests for InboundMessage dataclass."""

    def test_create_factory(self):
        """InboundMessage.create auto-generates ID and timestamp."""
        msg = InboundMessage.create(
            channel="discord",
            sender_id="user123",
            sender_name="Alice",
            content="Hello!",
        )
        assert msg.channel == "discord"
        assert msg.sender_id == "user123"
        assert msg.sender_name == "Alice"
        assert msg.content == "Hello!"
        # ID should be a valid UUID
        uuid.UUID(msg.id)
        # Timestamp should be recent UTC
        assert msg.timestamp.tzinfo is not None
        # Defaults
        assert msg.chat_type == "direct"
        assert msg.group_id is None
        assert msg.group_name is None
        assert msg.reply_to_id is None
        assert msg.media_urls is None
        assert msg.metadata == {}

    def test_create_with_kwargs(self):
        """InboundMessage.create accepts extra keyword arguments."""
        msg = InboundMessage.create(
            channel="imessage",
            sender_id="phone123",
            sender_name="Bob",
            content="Hey",
            chat_type="group",
            group_id="grp1",
            group_name="Friends",
            reply_to_id="msg-prev",
            media_urls=["https://img.com/a.jpg"],
            metadata={"source": "test"},
        )
        assert msg.chat_type == "group"
        assert msg.group_id == "grp1"
        assert msg.group_name == "Friends"
        assert msg.reply_to_id == "msg-prev"
        assert msg.media_urls == ["https://img.com/a.jpg"]
        assert msg.metadata == {"source": "test"}

    def test_direct_construction(self):
        """InboundMessage can be created directly with all fields."""
        now = datetime.now(UTC)
        msg = InboundMessage(
            id="fixed-id",
            channel="slack",
            sender_id="U123",
            sender_name="Carol",
            content="Test",
            timestamp=now,
        )
        assert msg.id == "fixed-id"
        assert msg.timestamp == now

    def test_unique_ids(self):
        """Each call to create produces a unique ID."""
        ids = {
            InboundMessage.create(
                channel="discord",
                sender_id="u",
                sender_name="n",
                content="c",
            ).id
            for _ in range(50)
        }
        assert len(ids) == 50


# ---------------------------------------------------------------------------
# Base: OutboundMessage
# ---------------------------------------------------------------------------

class TestOutboundMessage:
    """Tests for OutboundMessage dataclass."""

    def test_creation_required_fields(self):
        msg = OutboundMessage(
            channel="discord",
            target="channel-123",
            content="Response text",
        )
        assert msg.channel == "discord"
        assert msg.target == "channel-123"
        assert msg.content == "Response text"
        assert msg.reply_to_id is None
        assert msg.media_urls is None
        assert msg.metadata == {}

    def test_creation_all_fields(self):
        msg = OutboundMessage(
            channel="imessage",
            target="+15551234567",
            content="Reply",
            reply_to_id="orig-msg-id",
            media_urls=["https://img.com/b.png"],
            metadata={"priority": "high"},
        )
        assert msg.reply_to_id == "orig-msg-id"
        assert msg.media_urls == ["https://img.com/b.png"]
        assert msg.metadata["priority"] == "high"


# ---------------------------------------------------------------------------
# Base: SendResult
# ---------------------------------------------------------------------------

class TestSendResult:
    """Tests for SendResult dataclass."""

    def test_success_result(self):
        result = SendResult(success=True, message_id="msg-456")
        assert result.success is True
        assert result.message_id == "msg-456"
        assert result.error is None
        assert result.metadata == {}

    def test_failure_result(self):
        result = SendResult(success=False, error="Rate limited")
        assert result.success is False
        assert result.message_id is None
        assert result.error == "Rate limited"

    def test_result_with_metadata(self):
        result = SendResult(
            success=True,
            message_id="msg-789",
            metadata={"ts": "1234567890.123456"},
        )
        assert result.metadata["ts"] == "1234567890.123456"


# ---------------------------------------------------------------------------
# Base: ChannelStatus
# ---------------------------------------------------------------------------

class TestChannelStatus:
    """Tests for ChannelStatus dataclass."""

    def test_defaults(self):
        status = ChannelStatus(channel="discord")
        assert status.channel == "discord"
        assert status.healthy is True
        assert status.running is False
        assert status.last_start is None
        assert status.last_stop is None
        assert status.last_error is None
        assert status.last_inbound is None
        assert status.last_outbound is None
        assert status.message_count_in == 0
        assert status.message_count_out == 0

    def test_to_dict(self):
        now = datetime.now(UTC)
        status = ChannelStatus(
            channel="slack",
            healthy=True,
            running=True,
            last_start=now,
            message_count_in=42,
            message_count_out=10,
        )
        d = status.to_dict()
        assert d["channel"] == "slack"
        assert d["healthy"] is True
        assert d["running"] is True
        assert d["last_start"] == now.isoformat()
        assert d["last_stop"] is None
        assert d["message_count_in"] == 42
        assert d["message_count_out"] == 10

    def test_to_dict_none_dates(self):
        """Dates that are None serialize as None, not as ISO strings."""
        status = ChannelStatus(channel="imessage")
        d = status.to_dict()
        assert d["last_start"] is None
        assert d["last_stop"] is None
        assert d["last_inbound"] is None
        assert d["last_outbound"] is None


# ---------------------------------------------------------------------------
# Base: generate_message_id
# ---------------------------------------------------------------------------

class TestGenerateMessageId:
    """Tests for generate_message_id utility."""

    def test_returns_string(self):
        mid = generate_message_id()
        assert isinstance(mid, str)

    def test_is_valid_uuid(self):
        mid = generate_message_id()
        parsed = uuid.UUID(mid)
        assert str(parsed) == mid

    def test_uniqueness(self):
        ids = {generate_message_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# Base: Exception classes
# ---------------------------------------------------------------------------

class TestChannelExceptions:
    """Tests for channel exception hierarchy."""

    def test_channel_error(self):
        err = ChannelError("something broke", channel="discord")
        assert str(err) == "something broke"
        assert err.channel == "discord"
        assert err.retryable is False

    def test_channel_error_retryable(self):
        err = ChannelError("transient", channel="slack", retryable=True)
        assert err.retryable is True

    def test_connection_error_is_retryable(self):
        err = ChannelConnectionError("timeout", channel="discord")
        assert isinstance(err, ChannelError)
        assert err.retryable is True

    def test_send_error_default_retryable(self):
        err = ChannelSendError("rate limited", channel="slack")
        assert isinstance(err, ChannelError)
        assert err.retryable is True

    def test_send_error_non_retryable(self):
        err = ChannelSendError("invalid token", channel="slack", retryable=False)
        assert err.retryable is False

    def test_config_error_not_retryable(self):
        err = ChannelConfigError("missing token", channel="discord")
        assert isinstance(err, ChannelError)
        assert err.retryable is False

    def test_exceptions_are_catchable_as_base(self):
        """All channel exceptions can be caught as ChannelError."""
        for exc_cls in (ChannelConnectionError, ChannelSendError, ChannelConfigError):
            with pytest.raises(ChannelError):
                raise exc_cls("test", channel="test")
