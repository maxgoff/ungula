"""
Tests for messaging base types.

Covers InboundMessage, OutboundMessage, SendResult, ChannelStatus,
ChannelProvider (abstract), generate_message_id, and all exception classes.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ungula.messaging.base import (
    ChannelConfigError,
    ChannelConnectionError,
    ChannelError,
    ChannelProvider,
    ChannelSendError,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
    generate_message_id,
)


# ---------------------------------------------------------------------------
# generate_message_id
# ---------------------------------------------------------------------------


class TestGenerateMessageId:
    """Tests for the generate_message_id utility function."""

    def test_returns_string(self):
        """Return value is a string."""
        mid = generate_message_id()
        assert isinstance(mid, str)

    def test_valid_uuid4_format(self):
        """Generated ID is a valid UUID that roundtrips through uuid.UUID."""
        mid = generate_message_id()
        parsed = uuid.UUID(mid)
        assert str(parsed) == mid
        assert parsed.version == 4

    def test_uniqueness_across_calls(self):
        """Each call produces a distinct identifier."""
        ids = [generate_message_id() for _ in range(200)]
        assert len(set(ids)) == 200

    def test_not_empty(self):
        """Generated ID is never the empty string."""
        assert generate_message_id() != ""

    def test_consistent_length(self):
        """All generated IDs have the same string length (36 chars for UUID)."""
        lengths = {len(generate_message_id()) for _ in range(50)}
        assert lengths == {36}


# ---------------------------------------------------------------------------
# InboundMessage
# ---------------------------------------------------------------------------


class TestInboundMessage:
    """Tests for InboundMessage dataclass and its create() factory."""

    def test_create_generates_id(self):
        """create() auto-generates a valid UUID id."""
        msg = InboundMessage.create(
            channel="discord",
            sender_id="u1",
            sender_name="Alice",
            content="Hello",
        )
        uuid.UUID(msg.id)  # raises ValueError if invalid

    def test_create_generates_timestamp(self):
        """create() auto-generates a UTC timestamp close to now."""
        before = datetime.now(UTC)
        msg = InboundMessage.create(
            channel="discord",
            sender_id="u1",
            sender_name="Alice",
            content="Hello",
        )
        after = datetime.now(UTC)
        assert before <= msg.timestamp <= after

    def test_create_sets_required_fields(self):
        """create() correctly populates the four required fields."""
        msg = InboundMessage.create(
            channel="imessage",
            sender_id="phone-123",
            sender_name="Bob",
            content="Hey there",
        )
        assert msg.channel == "imessage"
        assert msg.sender_id == "phone-123"
        assert msg.sender_name == "Bob"
        assert msg.content == "Hey there"

    def test_create_defaults(self):
        """create() produces correct default values for optional fields."""
        msg = InboundMessage.create(
            channel="discord",
            sender_id="u1",
            sender_name="Alice",
            content="Hi",
        )
        assert msg.chat_type == "direct"
        assert msg.group_id is None
        assert msg.group_name is None
        assert msg.reply_to_id is None
        assert msg.media_urls is None
        assert msg.metadata == {}

    def test_create_with_all_kwargs(self):
        """create() forwards arbitrary keyword arguments to the dataclass."""
        msg = InboundMessage.create(
            channel="telegram",
            sender_id="tg-999",
            sender_name="Carol",
            content="Group message",
            chat_type="group",
            group_id="grp-42",
            group_name="Testers",
            reply_to_id="prev-msg",
            media_urls=["https://example.com/img.png", "https://example.com/img2.png"],
            metadata={"bot_command": True, "priority": 5},
        )
        assert msg.chat_type == "group"
        assert msg.group_id == "grp-42"
        assert msg.group_name == "Testers"
        assert msg.reply_to_id == "prev-msg"
        assert len(msg.media_urls) == 2
        assert msg.metadata["bot_command"] is True
        assert msg.metadata["priority"] == 5

    def test_create_unique_ids(self):
        """Successive calls to create() yield distinct IDs."""
        ids = {
            InboundMessage.create(
                channel="discord", sender_id="u", sender_name="n", content="c"
            ).id
            for _ in range(100)
        }
        assert len(ids) == 100

    def test_direct_construction(self):
        """InboundMessage can be created directly with explicit id and timestamp."""
        now = datetime.now(UTC)
        msg = InboundMessage(
            id="my-fixed-id",
            channel="slack",
            sender_id="U123",
            sender_name="Dave",
            content="Directly constructed",
            timestamp=now,
        )
        assert msg.id == "my-fixed-id"
        assert msg.timestamp == now
        assert msg.channel == "slack"

    def test_empty_content_allowed(self):
        """Messages with empty string content are valid."""
        msg = InboundMessage.create(
            channel="discord",
            sender_id="u1",
            sender_name="Alice",
            content="",
        )
        assert msg.content == ""

    def test_metadata_default_is_independent(self):
        """Each instance gets its own metadata dict (no shared mutable default)."""
        msg1 = InboundMessage.create(
            channel="discord", sender_id="u1", sender_name="A", content="x"
        )
        msg2 = InboundMessage.create(
            channel="discord", sender_id="u2", sender_name="B", content="y"
        )
        msg1.metadata["key"] = "val"
        assert "key" not in msg2.metadata

    def test_media_urls_none_by_default(self):
        """media_urls defaults to None, not an empty list."""
        msg = InboundMessage.create(
            channel="discord", sender_id="u1", sender_name="A", content="text"
        )
        assert msg.media_urls is None

    def test_timestamp_has_timezone(self):
        """Timestamp generated by create() is timezone-aware (UTC)."""
        msg = InboundMessage.create(
            channel="discord", sender_id="u1", sender_name="A", content="text"
        )
        assert msg.timestamp.tzinfo is not None

    def test_create_preserves_multiline_content(self):
        """Multi-line content is preserved exactly."""
        content = "Line 1\nLine 2\n\nLine 4"
        msg = InboundMessage.create(
            channel="discord", sender_id="u1", sender_name="A", content=content
        )
        assert msg.content == content

    def test_create_with_special_characters(self):
        """Content with unicode and special characters is preserved."""
        content = "Hello! \u2764\ufe0f \u00e9\u00e0\u00fc \u00a3100 \u2014 @user#1234"
        msg = InboundMessage.create(
            channel="discord", sender_id="u1", sender_name="A", content=content
        )
        assert msg.content == content

    def test_create_with_empty_media_urls_list(self):
        """Explicit empty list for media_urls is accepted."""
        msg = InboundMessage.create(
            channel="discord",
            sender_id="u1",
            sender_name="A",
            content="text",
            media_urls=[],
        )
        assert msg.media_urls == []


# ---------------------------------------------------------------------------
# OutboundMessage
# ---------------------------------------------------------------------------


class TestOutboundMessage:
    """Tests for OutboundMessage dataclass."""

    def test_required_fields_only(self):
        """Creation with only required fields succeeds and defaults are correct."""
        msg = OutboundMessage(
            channel="discord",
            target="channel-456",
            content="Reply text",
        )
        assert msg.channel == "discord"
        assert msg.target == "channel-456"
        assert msg.content == "Reply text"
        assert msg.reply_to_id is None
        assert msg.media_urls is None
        assert msg.metadata == {}

    def test_all_fields(self):
        """All optional fields can be populated."""
        msg = OutboundMessage(
            channel="imessage",
            target="+15551234567",
            content="Here is the file",
            reply_to_id="orig-123",
            media_urls=["https://cdn.example.com/file.pdf"],
            metadata={"delivery": "express"},
        )
        assert msg.reply_to_id == "orig-123"
        assert msg.media_urls == ["https://cdn.example.com/file.pdf"]
        assert msg.metadata["delivery"] == "express"

    def test_metadata_default_is_independent(self):
        """Each instance gets its own metadata dict."""
        msg1 = OutboundMessage(channel="a", target="t", content="c")
        msg2 = OutboundMessage(channel="b", target="t", content="c")
        msg1.metadata["key"] = "val"
        assert "key" not in msg2.metadata

    def test_empty_content(self):
        """Empty string content is valid."""
        msg = OutboundMessage(channel="discord", target="ch", content="")
        assert msg.content == ""

    def test_multiple_media_urls(self):
        """Multiple media URLs can be attached."""
        urls = [f"https://cdn.example.com/img{i}.png" for i in range(5)]
        msg = OutboundMessage(
            channel="telegram", target="chat-1", content="Images", media_urls=urls
        )
        assert len(msg.media_urls) == 5

    def test_channel_types(self):
        """Various channel strings are accepted without restriction."""
        for ch in ("discord", "imessage", "telegram", "slack", "signal", "custom"):
            msg = OutboundMessage(channel=ch, target="t", content="c")
            assert msg.channel == ch

    def test_long_content(self):
        """Very long content strings are accepted."""
        long_content = "A" * 50_000
        msg = OutboundMessage(channel="discord", target="ch", content=long_content)
        assert len(msg.content) == 50_000


# ---------------------------------------------------------------------------
# SendResult
# ---------------------------------------------------------------------------


class TestSendResult:
    """Tests for SendResult dataclass."""

    def test_success_with_message_id(self):
        """Successful result with a message ID."""
        result = SendResult(success=True, message_id="msg-abc-123")
        assert result.success is True
        assert result.message_id == "msg-abc-123"
        assert result.error is None
        assert result.metadata == {}

    def test_failure_with_error(self):
        """Failed result with an error string."""
        result = SendResult(success=False, error="Rate limited")
        assert result.success is False
        assert result.message_id is None
        assert result.error == "Rate limited"

    def test_success_with_metadata(self):
        """Metadata can carry extra provider-specific info."""
        result = SendResult(
            success=True,
            message_id="m1",
            metadata={"ts": "1234567890.123456", "channel_id": "C123"},
        )
        assert result.metadata["ts"] == "1234567890.123456"
        assert result.metadata["channel_id"] == "C123"

    def test_failure_no_message_id(self):
        """Default message_id is None on failure."""
        result = SendResult(success=False, error="timeout")
        assert result.message_id is None

    def test_defaults(self):
        """Minimal construction sets correct defaults."""
        result = SendResult(success=True)
        assert result.message_id is None
        assert result.error is None
        assert result.metadata == {}

    def test_metadata_default_is_independent(self):
        """Each SendResult gets its own metadata dict."""
        r1 = SendResult(success=True)
        r2 = SendResult(success=True)
        r1.metadata["k"] = "v"
        assert "k" not in r2.metadata

    def test_failure_with_metadata(self):
        """Failed results can also carry metadata (e.g. HTTP status code)."""
        result = SendResult(
            success=False,
            error="server error",
            metadata={"status_code": 500},
        )
        assert result.metadata["status_code"] == 500


# ---------------------------------------------------------------------------
# ChannelStatus
# ---------------------------------------------------------------------------


class TestChannelStatus:
    """Tests for ChannelStatus dataclass and its to_dict() method."""

    def test_defaults(self):
        """Default values are correct for a new channel."""
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

    def test_to_dict_with_none_datetimes(self):
        """to_dict serializes None datetime fields as None."""
        status = ChannelStatus(channel="imessage")
        d = status.to_dict()
        assert d["last_start"] is None
        assert d["last_stop"] is None
        assert d["last_inbound"] is None
        assert d["last_outbound"] is None

    def test_to_dict_with_datetime_values(self):
        """to_dict serializes datetime fields as ISO format strings."""
        now = datetime.now(UTC)
        status = ChannelStatus(
            channel="slack",
            healthy=True,
            running=True,
            last_start=now,
            last_stop=now - timedelta(hours=1),
            last_inbound=now - timedelta(minutes=5),
            last_outbound=now - timedelta(minutes=2),
            message_count_in=42,
            message_count_out=10,
        )
        d = status.to_dict()
        assert d["channel"] == "slack"
        assert d["healthy"] is True
        assert d["running"] is True
        assert d["last_start"] == now.isoformat()
        assert d["last_stop"] == (now - timedelta(hours=1)).isoformat()
        assert d["last_inbound"] == (now - timedelta(minutes=5)).isoformat()
        assert d["last_outbound"] == (now - timedelta(minutes=2)).isoformat()
        assert d["message_count_in"] == 42
        assert d["message_count_out"] == 10

    def test_to_dict_contains_all_keys(self):
        """to_dict returns exactly the expected set of keys."""
        status = ChannelStatus(channel="test")
        expected_keys = {
            "channel",
            "healthy",
            "running",
            "last_start",
            "last_stop",
            "last_error",
            "last_inbound",
            "last_outbound",
            "message_count_in",
            "message_count_out",
        }
        assert set(status.to_dict().keys()) == expected_keys

    def test_to_dict_with_error(self):
        """to_dict includes the last_error string."""
        status = ChannelStatus(channel="discord", last_error="Connection refused")
        d = status.to_dict()
        assert d["last_error"] == "Connection refused"

    def test_to_dict_returns_plain_dict(self):
        """to_dict returns a plain dict, not a dataclass or other type."""
        status = ChannelStatus(channel="test")
        d = status.to_dict()
        assert type(d) is dict

    def test_mutable_fields(self):
        """Status fields can be updated after creation."""
        status = ChannelStatus(channel="discord")
        assert status.running is False
        status.running = True
        status.message_count_in = 5
        assert status.running is True
        assert status.message_count_in == 5

    def test_to_dict_datetime_iso_format_contains_t(self):
        """ISO format datetime strings contain 'T' separator."""
        now = datetime.now(UTC)
        status = ChannelStatus(channel="test", last_start=now)
        d = status.to_dict()
        assert "T" in d["last_start"]

    def test_multiple_channels_independent(self):
        """Separate ChannelStatus instances are independent."""
        s1 = ChannelStatus(channel="discord")
        s2 = ChannelStatus(channel="telegram")
        s1.message_count_in = 100
        assert s2.message_count_in == 0

    def test_unhealthy_status(self):
        """ChannelStatus can represent an unhealthy channel."""
        status = ChannelStatus(
            channel="discord",
            healthy=False,
            running=True,
            last_error="Websocket timeout",
        )
        d = status.to_dict()
        assert d["healthy"] is False
        assert d["running"] is True
        assert d["last_error"] == "Websocket timeout"


# ---------------------------------------------------------------------------
# ChannelProvider (abstract)
# ---------------------------------------------------------------------------


class ConcreteProvider(ChannelProvider):
    """Minimal concrete implementation for testing the abstract base class."""

    name = "concrete"
    display_name = "Concrete Test Channel"

    def __init__(self):
        self.started = False
        self.stopped = False
        self._healthy = True

    async def start(self, config: Any, on_message: MessageCallback) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, message: OutboundMessage) -> SendResult:
        return SendResult(success=True, message_id="test-msg-id")

    async def check_health(self) -> bool:
        return self._healthy

    def get_status(self) -> ChannelStatus:
        return ChannelStatus(channel=self.name, running=self.started)


class TestChannelProvider:
    """Tests for the ChannelProvider abstract base class."""

    async def test_concrete_start(self):
        """Concrete provider's start() can be called."""
        provider = ConcreteProvider()
        callback = AsyncMock()
        await provider.start({}, callback)
        assert provider.started is True

    async def test_concrete_stop(self):
        """Concrete provider's stop() can be called."""
        provider = ConcreteProvider()
        await provider.stop()
        assert provider.stopped is True

    async def test_concrete_send(self):
        """Concrete provider's send() returns a SendResult."""
        provider = ConcreteProvider()
        msg = OutboundMessage(channel="concrete", target="t", content="c")
        result = await provider.send(msg)
        assert result.success is True
        assert result.message_id == "test-msg-id"

    async def test_concrete_check_health(self):
        """Concrete provider's check_health() returns a boolean."""
        provider = ConcreteProvider()
        assert await provider.check_health() is True

    async def test_concrete_get_status(self):
        """Concrete provider's get_status() returns ChannelStatus."""
        provider = ConcreteProvider()
        status = provider.get_status()
        assert isinstance(status, ChannelStatus)
        assert status.channel == "concrete"

    async def test_typing_start_default_noop(self):
        """Default typing_start() is a no-op (does not raise)."""
        provider = ConcreteProvider()
        await provider.typing_start("target-123")  # should not raise

    async def test_react_default_noop(self):
        """Default react() is a no-op (does not raise)."""
        provider = ConcreteProvider()
        await provider.react("ch-1", "msg-1", "thumbsup")  # should not raise

    def test_cannot_instantiate_abstract(self):
        """ChannelProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ChannelProvider()  # type: ignore[abstract]

    def test_provider_has_name_and_display_name(self):
        """Concrete provider exposes name and display_name attributes."""
        provider = ConcreteProvider()
        assert provider.name == "concrete"
        assert provider.display_name == "Concrete Test Channel"


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class TestChannelError:
    """Tests for the base ChannelError exception."""

    def test_message_and_channel(self):
        """ChannelError stores message and channel attributes."""
        err = ChannelError("something broke", channel="discord")
        assert str(err) == "something broke"
        assert err.channel == "discord"

    def test_default_not_retryable(self):
        """ChannelError defaults to retryable=False."""
        err = ChannelError("failure", channel="slack")
        assert err.retryable is False

    def test_explicit_retryable(self):
        """ChannelError can be marked retryable."""
        err = ChannelError("transient issue", channel="slack", retryable=True)
        assert err.retryable is True

    def test_is_exception(self):
        """ChannelError is an Exception subclass."""
        err = ChannelError("test", channel="test")
        assert isinstance(err, Exception)

    def test_raises_and_catches(self):
        """ChannelError can be raised and caught."""
        with pytest.raises(ChannelError) as exc_info:
            raise ChannelError("oops", channel="discord")
        assert exc_info.value.channel == "discord"


class TestChannelConnectionError:
    """Tests for ChannelConnectionError."""

    def test_always_retryable(self):
        """Connection errors are always retryable."""
        err = ChannelConnectionError("timeout", channel="discord")
        assert err.retryable is True

    def test_is_channel_error(self):
        """ChannelConnectionError is a subclass of ChannelError."""
        err = ChannelConnectionError("conn refused", channel="slack")
        assert isinstance(err, ChannelError)

    def test_message_preserved(self):
        """Error message is preserved in str()."""
        err = ChannelConnectionError("DNS lookup failed", channel="telegram")
        assert str(err) == "DNS lookup failed"
        assert err.channel == "telegram"

    def test_catchable_as_base(self):
        """Can be caught with except ChannelError."""
        with pytest.raises(ChannelError):
            raise ChannelConnectionError("test", channel="test")


class TestChannelSendError:
    """Tests for ChannelSendError."""

    def test_default_retryable(self):
        """Send errors default to retryable=True."""
        err = ChannelSendError("rate limited", channel="discord")
        assert err.retryable is True

    def test_explicit_non_retryable(self):
        """Send errors can be marked non-retryable."""
        err = ChannelSendError("invalid token", channel="slack", retryable=False)
        assert err.retryable is False

    def test_is_channel_error(self):
        """ChannelSendError is a subclass of ChannelError."""
        err = ChannelSendError("failed", channel="telegram")
        assert isinstance(err, ChannelError)

    def test_channel_attribute(self):
        """Channel attribute is correctly set."""
        err = ChannelSendError("error", channel="imessage")
        assert err.channel == "imessage"

    def test_catchable_as_base(self):
        """Can be caught with except ChannelError."""
        with pytest.raises(ChannelError):
            raise ChannelSendError("test", channel="test")


class TestChannelConfigError:
    """Tests for ChannelConfigError."""

    def test_always_not_retryable(self):
        """Config errors are never retryable."""
        err = ChannelConfigError("missing API key", channel="discord")
        assert err.retryable is False

    def test_is_channel_error(self):
        """ChannelConfigError is a subclass of ChannelError."""
        err = ChannelConfigError("bad config", channel="slack")
        assert isinstance(err, ChannelError)

    def test_message_preserved(self):
        """Error message is preserved."""
        err = ChannelConfigError("invalid port number", channel="telegram")
        assert str(err) == "invalid port number"
        assert err.channel == "telegram"

    def test_catchable_as_base(self):
        """Can be caught with except ChannelError."""
        with pytest.raises(ChannelError):
            raise ChannelConfigError("test", channel="test")


class TestExceptionHierarchyCatchAll:
    """Cross-cutting tests for the full exception hierarchy."""

    def test_all_subclasses_caught_by_channel_error(self):
        """Every channel-specific exception can be caught as ChannelError."""
        for cls, kwargs in [
            (ChannelConnectionError, {"message": "err", "channel": "c"}),
            (ChannelSendError, {"message": "err", "channel": "c"}),
            (ChannelConfigError, {"message": "err", "channel": "c"}),
        ]:
            with pytest.raises(ChannelError):
                raise cls(**kwargs)

    def test_subclass_identity(self):
        """Specific exception types maintain their identity even when caught broadly."""
        try:
            raise ChannelConnectionError("test", channel="discord")
        except ChannelError as e:
            assert isinstance(e, ChannelConnectionError)

    def test_different_channels_same_error_type(self):
        """Same error type can be used for different channels."""
        err_discord = ChannelConnectionError("down", channel="discord")
        err_slack = ChannelConnectionError("down", channel="slack")
        assert err_discord.channel != err_slack.channel
        assert err_discord.retryable == err_slack.retryable
