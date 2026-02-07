"""
Tests for the ChannelRegistry.

Covers registration, lifecycle management (start/stop), message sending,
health checks, status reporting, inbound recording, and teardown.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ungula.messaging.base import (
    ChannelError,
    ChannelProvider,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
)
from ungula.messaging.registry import ChannelRegistry


# ---------------------------------------------------------------------------
# MockChannelProvider
# ---------------------------------------------------------------------------


class MockChannelProvider(ChannelProvider):
    """
    In-memory channel provider for testing the registry.

    Tracks calls to start/stop/send/health so tests can assert on them.
    """

    name = "mock"
    display_name = "Mock Channel"

    def __init__(
        self,
        *,
        name: str = "mock",
        healthy: bool = True,
        send_success: bool = True,
        start_raises: Exception | None = None,
        stop_raises: Exception | None = None,
        send_raises: Exception | None = None,
        health_raises: Exception | None = None,
    ):
        self.name = name
        self.display_name = f"Mock {name.title()}"
        self._healthy = healthy
        self._send_success = send_success
        self._start_raises = start_raises
        self._stop_raises = stop_raises
        self._send_raises = send_raises
        self._health_raises = health_raises
        self.started = False
        self.stopped = False
        self.start_call_count = 0
        self.stop_call_count = 0
        self.send_call_count = 0
        self.health_call_count = 0
        self.last_config: Any = None
        self.last_callback: MessageCallback | None = None
        self.last_sent_message: OutboundMessage | None = None

    async def start(self, config: Any, on_message: MessageCallback) -> None:
        self.start_call_count += 1
        if self._start_raises:
            raise self._start_raises
        self.started = True
        self.last_config = config
        self.last_callback = on_message

    async def stop(self) -> None:
        self.stop_call_count += 1
        if self._stop_raises:
            raise self._stop_raises
        self.stopped = True

    async def send(self, message: OutboundMessage) -> SendResult:
        self.send_call_count += 1
        self.last_sent_message = message
        if self._send_raises:
            raise self._send_raises
        if self._send_success:
            return SendResult(success=True, message_id="mock-msg-001")
        return SendResult(success=False, error="Mock send failure")

    async def check_health(self) -> bool:
        self.health_call_count += 1
        if self._health_raises:
            raise self._health_raises
        return self._healthy

    def get_status(self) -> ChannelStatus:
        return ChannelStatus(
            channel=self.name,
            healthy=self._healthy,
            running=self.started,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_callback() -> AsyncMock:
    """Create an async callback suitable for MessageCallback."""
    return AsyncMock()


def _make_outbound(channel: str = "mock") -> OutboundMessage:
    """Create a minimal outbound message for the given channel."""
    return OutboundMessage(channel=channel, target="target-1", content="Test message")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    """Tests for register / unregister / get / list_channels."""

    def test_register_adds_provider(self):
        """register() makes the provider available via get()."""
        registry = ChannelRegistry()
        provider = MockChannelProvider()
        registry.register(provider)
        assert registry.get("mock") is provider

    def test_register_creates_status(self):
        """register() initializes a ChannelStatus entry."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        assert "mock" in registry.status
        assert registry.status["mock"].channel == "mock"

    def test_unregister_removes_provider(self):
        """unregister() removes the provider so get() returns None."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry.unregister("mock")
        assert registry.get("mock") is None

    def test_unregister_removes_status(self):
        """unregister() also cleans up the status entry."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry.unregister("mock")
        assert "mock" not in registry.status

    def test_unregister_nonexistent_no_error(self):
        """unregister() for an unknown name does not raise."""
        registry = ChannelRegistry()
        registry.unregister("does-not-exist")  # should not raise

    def test_get_nonexistent_returns_none(self):
        """get() returns None for an unknown channel name."""
        registry = ChannelRegistry()
        assert registry.get("unknown") is None

    def test_list_channels_empty(self):
        """list_channels() returns empty list when no providers registered."""
        registry = ChannelRegistry()
        assert registry.list_channels() == []

    def test_list_channels(self):
        """list_channels() returns names of all registered providers."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="discord"))
        registry.register(MockChannelProvider(name="telegram"))
        names = registry.list_channels()
        assert set(names) == {"discord", "telegram"}

    def test_register_overwrites_same_name(self):
        """Registering with the same name replaces the previous provider."""
        registry = ChannelRegistry()
        p1 = MockChannelProvider(name="mock")
        p2 = MockChannelProvider(name="mock")
        registry.register(p1)
        registry.register(p2)
        assert registry.get("mock") is p2

    def test_is_running_false_by_default(self):
        """is_running() returns False before start_channel is called."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        assert registry.is_running("mock") is False

    def test_is_running_unknown_channel(self):
        """is_running() returns False for an unknown channel."""
        registry = ChannelRegistry()
        assert registry.is_running("nonexistent") is False


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for start_channel / stop_channel and related lifecycle methods."""

    async def test_start_channel_calls_provider_start(self):
        """start_channel() invokes the provider's start() method."""
        registry = ChannelRegistry()
        provider = MockChannelProvider()
        registry.register(provider)
        registry._on_message = _make_callback()

        await registry.start_channel("mock")

        assert provider.start_call_count == 1
        assert provider.started is True

    async def test_start_channel_sets_running(self):
        """start_channel() marks the channel status as running."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()

        await registry.start_channel("mock")

        assert registry.status["mock"].running is True
        assert registry.is_running("mock") is True

    async def test_start_channel_sets_last_start(self):
        """start_channel() records the start time."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()

        before = datetime.now(UTC)
        await registry.start_channel("mock")
        after = datetime.now(UTC)

        assert registry.status["mock"].last_start is not None
        assert before <= registry.status["mock"].last_start <= after

    async def test_start_channel_clears_last_error(self):
        """Successful start clears any previous error."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()
        registry.status["mock"].last_error = "previous error"

        await registry.start_channel("mock")

        assert registry.status["mock"].last_error is None

    async def test_start_channel_unknown_raises(self):
        """start_channel() raises ChannelError for unknown channel."""
        registry = ChannelRegistry()
        registry._on_message = _make_callback()

        with pytest.raises(ChannelError):
            await registry.start_channel("nonexistent")

    async def test_start_channel_no_callback_raises(self):
        """start_channel() raises ChannelError when no callback is set."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        with pytest.raises(ChannelError):
            await registry.start_channel("mock")

    async def test_start_channel_provider_failure_records_error(self):
        """If provider.start() raises, the error is recorded in status."""
        provider = MockChannelProvider(start_raises=RuntimeError("connection failed"))
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()

        with pytest.raises(RuntimeError):
            await registry.start_channel("mock")

        assert registry.status["mock"].running is False
        assert "connection failed" in registry.status["mock"].last_error

    async def test_start_channel_with_config(self):
        """start_channel() passes config to the provider."""
        provider = MockChannelProvider()
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()

        config = {"token": "abc123"}
        await registry.start_channel("mock", config=config)

        assert provider.last_config == config

    async def test_stop_channel_calls_provider_stop(self):
        """stop_channel() invokes the provider's stop() method."""
        registry = ChannelRegistry()
        provider = MockChannelProvider()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        await registry.stop_channel("mock")

        assert provider.stop_call_count == 1
        assert provider.stopped is True

    async def test_stop_channel_clears_running(self):
        """stop_channel() sets running to False."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        await registry.stop_channel("mock")

        assert registry.status["mock"].running is False
        assert registry.is_running("mock") is False

    async def test_stop_channel_records_last_stop(self):
        """stop_channel() records the stop timestamp."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        before = datetime.now(UTC)
        await registry.stop_channel("mock")
        after = datetime.now(UTC)

        assert registry.status["mock"].last_stop is not None
        assert before <= registry.status["mock"].last_stop <= after

    async def test_stop_channel_unknown_no_error(self):
        """stop_channel() for an unknown channel does not raise."""
        registry = ChannelRegistry()
        await registry.stop_channel("nonexistent")  # should not raise

    async def test_stop_channel_provider_failure_records_error(self):
        """If provider.stop() raises, the error is recorded but not re-raised."""
        provider = MockChannelProvider(stop_raises=RuntimeError("shutdown error"))
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        # stop_channel catches the exception internally
        await registry.stop_channel("mock")

        assert "shutdown error" in registry.status["mock"].last_error


# ---------------------------------------------------------------------------
# Sending messages
# ---------------------------------------------------------------------------


class TestSend:
    """Tests for the send() method."""

    async def test_send_to_running_channel(self):
        """Sending to a running channel returns success."""
        registry = ChannelRegistry()
        provider = MockChannelProvider()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        result = await registry.send(_make_outbound("mock"))

        assert result.success is True
        assert result.message_id == "mock-msg-001"

    async def test_send_increments_outbound_count(self):
        """Successful send increments message_count_out."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        await registry.send(_make_outbound("mock"))
        await registry.send(_make_outbound("mock"))

        assert registry.status["mock"].message_count_out == 2

    async def test_send_records_last_outbound(self):
        """Successful send updates last_outbound timestamp."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        before = datetime.now(UTC)
        await registry.send(_make_outbound("mock"))
        after = datetime.now(UTC)

        assert registry.status["mock"].last_outbound is not None
        assert before <= registry.status["mock"].last_outbound <= after

    async def test_send_to_not_running_channel(self):
        """Sending to a registered but not running channel returns error."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        # Not started

        result = await registry.send(_make_outbound("mock"))

        assert result.success is False
        assert "not running" in result.error.lower()

    async def test_send_to_unknown_channel(self):
        """Sending to an unregistered channel returns error."""
        registry = ChannelRegistry()

        result = await registry.send(_make_outbound("nonexistent"))

        assert result.success is False
        assert "unknown" in result.error.lower() or "Unknown" in result.error

    async def test_send_provider_raises_returns_error(self):
        """If the provider's send() raises, the result is a failure."""
        provider = MockChannelProvider(send_raises=RuntimeError("network error"))
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        result = await registry.send(_make_outbound("mock"))

        assert result.success is False
        assert "network error" in result.error

    async def test_send_provider_returns_failure(self):
        """If the provider's send() returns failure, it propagates."""
        provider = MockChannelProvider(send_success=False)
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        result = await registry.send(_make_outbound("mock"))

        assert result.success is False

    async def test_send_passes_message_to_provider(self):
        """The outbound message is forwarded to the provider's send()."""
        provider = MockChannelProvider()
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        msg = _make_outbound("mock")
        await registry.send(msg)

        assert provider.last_sent_message is msg

    async def test_send_failed_does_not_increment_count(self):
        """Failed send does not increment outbound message counter."""
        provider = MockChannelProvider(send_success=False)
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        await registry.send(_make_outbound("mock"))

        assert registry.status["mock"].message_count_out == 0


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Tests for check_health()."""

    async def test_check_health_single_channel(self):
        """check_health with a specific name returns dict with one entry."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="discord", healthy=True))

        result = await registry.check_health("discord")

        assert result == {"discord": True}

    async def test_check_health_all_channels(self):
        """check_health with name=None checks all channels."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="discord", healthy=True))
        registry.register(MockChannelProvider(name="telegram", healthy=False))

        result = await registry.check_health()

        assert result["discord"] is True
        assert result["telegram"] is False

    async def test_check_health_updates_status(self):
        """check_health updates the status.healthy field."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="mock", healthy=False))

        await registry.check_health("mock")

        assert registry.status["mock"].healthy is False

    async def test_check_health_provider_raises(self):
        """If check_health() raises, the channel is marked unhealthy."""
        provider = MockChannelProvider(
            name="broken",
            health_raises=RuntimeError("health check failed"),
        )
        registry = ChannelRegistry()
        registry.register(provider)

        result = await registry.check_health("broken")

        assert result["broken"] is False
        assert registry.status["broken"].healthy is False

    async def test_check_health_unknown_channel(self):
        """Checking health of an unknown channel returns False."""
        registry = ChannelRegistry()

        result = await registry.check_health("nonexistent")

        assert result["nonexistent"] is False

    async def test_check_health_calls_provider(self):
        """check_health actually invokes the provider's check_health method."""
        provider = MockChannelProvider()
        registry = ChannelRegistry()
        registry.register(provider)

        await registry.check_health("mock")

        assert provider.health_call_count == 1

    async def test_check_health_no_channels(self):
        """check_health() with no channels returns empty dict."""
        registry = ChannelRegistry()

        result = await registry.check_health()

        assert result == {}


# ---------------------------------------------------------------------------
# Status reporting
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for get_status()."""

    def test_get_status_empty(self):
        """get_status() with no channels returns empty dict."""
        registry = ChannelRegistry()
        assert registry.get_status() == {}

    def test_get_status_returns_dict_of_dicts(self):
        """get_status() returns channel name -> dict mapping."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="discord"))
        registry.register(MockChannelProvider(name="telegram"))

        status = registry.get_status()

        assert "discord" in status
        assert "telegram" in status
        assert isinstance(status["discord"], dict)
        assert isinstance(status["telegram"], dict)

    def test_get_status_contains_expected_keys(self):
        """Each status dict has all the ChannelStatus.to_dict() keys."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        status = registry.get_status()
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
        assert set(status["mock"].keys()) == expected_keys

    def test_get_status_reflects_channel_name(self):
        """The 'channel' key in each status matches the registration name."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="slack"))

        status = registry.get_status()

        assert status["slack"]["channel"] == "slack"


# ---------------------------------------------------------------------------
# Inbound recording
# ---------------------------------------------------------------------------


class TestRecordInbound:
    """Tests for record_inbound()."""

    def test_record_inbound_increments_count(self):
        """record_inbound() increments message_count_in."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        registry.record_inbound("mock")
        registry.record_inbound("mock")
        registry.record_inbound("mock")

        assert registry.status["mock"].message_count_in == 3

    def test_record_inbound_sets_last_inbound(self):
        """record_inbound() updates last_inbound timestamp."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        before = datetime.now(UTC)
        registry.record_inbound("mock")
        after = datetime.now(UTC)

        assert registry.status["mock"].last_inbound is not None
        assert before <= registry.status["mock"].last_inbound <= after

    def test_record_inbound_unknown_channel_no_error(self):
        """record_inbound() for an unknown channel is a no-op."""
        registry = ChannelRegistry()
        registry.record_inbound("nonexistent")  # should not raise

    def test_record_inbound_multiple_channels(self):
        """record_inbound() tracks counts per channel independently."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider(name="discord"))
        registry.register(MockChannelProvider(name="telegram"))

        registry.record_inbound("discord")
        registry.record_inbound("discord")
        registry.record_inbound("telegram")

        assert registry.status["discord"].message_count_in == 2
        assert registry.status["telegram"].message_count_in == 1


# ---------------------------------------------------------------------------
# Close / teardown
# ---------------------------------------------------------------------------


class TestClose:
    """Tests for the close() method."""

    async def test_close_stops_running_channels(self):
        """close() stops providers that have entries in _tasks."""
        provider = MockChannelProvider()
        registry = ChannelRegistry()
        registry.register(provider)
        registry._on_message = _make_callback()
        await registry.start_channel("mock")

        # Simulate a running task entry (normally set by real providers)
        loop = asyncio.get_event_loop()
        dummy_task = loop.create_task(asyncio.sleep(100))
        registry._tasks["mock"] = dummy_task

        await registry.close()

        assert provider.stopped is True
        assert dummy_task.cancelled()

    async def test_close_clears_channels(self):
        """close() empties the channels dict."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        await registry.close()

        assert registry.list_channels() == []
        assert registry.get("mock") is None

    async def test_close_clears_status(self):
        """close() empties the status dict."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        await registry.close()

        assert registry.get_status() == {}

    async def test_close_idempotent(self):
        """Calling close() multiple times does not raise."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())

        await registry.close()
        await registry.close()  # should not raise

    async def test_close_empty_registry(self):
        """close() on empty registry does not raise."""
        registry = ChannelRegistry()
        await registry.close()  # should not raise


# ---------------------------------------------------------------------------
# start_all / stop_all
# ---------------------------------------------------------------------------


class TestStartStopAll:
    """Tests for start_all / stop_all convenience methods."""

    async def test_start_all_starts_every_channel(self):
        """start_all() starts all registered providers."""
        p1 = MockChannelProvider(name="discord")
        p2 = MockChannelProvider(name="telegram")
        registry = ChannelRegistry()
        registry.register(p1)
        registry.register(p2)

        callback = _make_callback()
        await registry.start_all(callback)

        assert p1.started is True
        assert p2.started is True

    async def test_start_all_stores_callback(self):
        """start_all() stores the on_message callback."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        callback = _make_callback()

        await registry.start_all(callback)

        assert registry._on_message is callback

    async def test_start_all_one_failure_continues(self):
        """If one channel fails to start, others still start."""
        p_ok = MockChannelProvider(name="ok")
        p_bad = MockChannelProvider(name="bad", start_raises=RuntimeError("boom"))
        registry = ChannelRegistry()
        registry.register(p_bad)
        registry.register(p_ok)

        await registry.start_all(_make_callback())

        assert p_ok.started is True
        assert p_bad.started is False

    async def test_stop_all_stops_channels_with_tasks(self):
        """stop_all() stops providers that have entries in _tasks."""
        p1 = MockChannelProvider(name="discord")
        p2 = MockChannelProvider(name="telegram")
        registry = ChannelRegistry()
        registry.register(p1)
        registry.register(p2)
        await registry.start_all(_make_callback())

        # Simulate running task entries for both channels
        loop = asyncio.get_event_loop()
        registry._tasks["discord"] = loop.create_task(asyncio.sleep(100))
        registry._tasks["telegram"] = loop.create_task(asyncio.sleep(100))

        await registry.stop_all()

        assert p1.stopped is True
        assert p2.stopped is True

    async def test_stop_all_only_iterates_tasks(self):
        """stop_all() only iterates _tasks, not channels without tasks."""
        provider = MockChannelProvider()
        registry = ChannelRegistry()
        registry.register(provider)
        await registry.start_all(_make_callback())

        # No task entries -- stop_all should not call provider.stop()
        await registry.stop_all()

        assert provider.stopped is False

    async def test_stop_all_clears_callback(self):
        """stop_all() clears the on_message callback."""
        registry = ChannelRegistry()
        registry.register(MockChannelProvider())
        await registry.start_all(_make_callback())

        await registry.stop_all()

        assert registry._on_message is None
