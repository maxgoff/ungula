"""
Tests for the event bus system.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ungula.events.actions import ActionExecutor
from ungula.events.bus import EventBus
from ungula.events.store import EventRuleStore
from ungula.events.types import ActionType, Event, EventRule, EventType


# --- Event / EventRule model tests ---


class TestEventTypes:
    """Tests for event type models."""

    def test_event_defaults(self):
        e = Event(type="test")
        assert e.type == "test"
        assert e.data == {}
        assert e.id  # auto-generated
        assert e.timestamp

    def test_event_with_data(self):
        e = Event(type="message.received", data={"channel": "discord"})
        assert e.data["channel"] == "discord"

    def test_event_rule_defaults(self):
        r = EventRule(name="test", event_type="message.received", action="log")
        assert r.enabled is True
        assert r.fire_count == 0
        assert r.filters == {}

    def test_event_type_enum(self):
        assert EventType.MESSAGE_RECEIVED == "message.received"
        assert EventType.CRON_FIRED == "cron.fired"

    def test_action_type_enum(self):
        assert ActionType.RUN_AGENT == "run_agent"
        assert ActionType.LOG == "log"


# --- EventRuleStore tests ---


class TestEventRuleStore:
    """Tests for EventRuleStore CRUD."""

    def test_add_and_get(self):
        store = EventRuleStore()
        rule = EventRule(name="r1", event_type="test", action="log")
        added = store.add(rule)
        assert added.id
        assert store.get(added.id) is added

    def test_list_all(self):
        store = EventRuleStore()
        store.add(EventRule(name="a", event_type="t", action="log"))
        store.add(EventRule(name="b", event_type="t", action="log", enabled=False))

        assert len(store.list_all()) == 2
        assert len(store.list_all(enabled_only=True)) == 1

    def test_list_by_event_type(self):
        store = EventRuleStore()
        store.add(EventRule(name="a", event_type="x", action="log"))
        store.add(EventRule(name="b", event_type="y", action="log"))
        store.add(EventRule(name="c", event_type="x", action="log", enabled=False))

        matches = store.list_by_event_type("x")
        assert len(matches) == 1  # only enabled

    def test_update(self):
        store = EventRuleStore()
        rule = store.add(EventRule(name="old", event_type="t", action="log"))
        updated = store.update(rule.id, name="new")
        assert updated.name == "new"

    def test_update_nonexistent(self):
        store = EventRuleStore()
        assert store.update("nope", name="new") is None

    def test_delete(self):
        store = EventRuleStore()
        rule = store.add(EventRule(name="r1", event_type="t", action="log"))
        assert store.delete(rule.id) is True
        assert store.get(rule.id) is None
        assert store.delete(rule.id) is False

    def test_mark_fired(self):
        store = EventRuleStore()
        rule = store.add(EventRule(name="r1", event_type="t", action="log"))
        store.mark_fired(rule.id)
        assert rule.fire_count == 1
        assert rule.last_fired is not None


# --- EventBus tests ---


class TestEventBus:
    """Tests for EventBus."""

    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self):
        """Programmatic subscriber receives events."""
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.emit(Event(type="test.event", data={"key": "val"}))

        # Wait for fire-and-forget task
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].data["key"] == "val"

    @pytest.mark.asyncio
    async def test_subscriber_only_gets_matching_type(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("type_a", handler)
        bus.emit(Event(type="type_b"))

        await asyncio.sleep(0.05)
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_rule_based_dispatch(self):
        """Rules trigger action executor."""
        store = EventRuleStore()
        executor = AsyncMock()
        bus = EventBus(store=store, action_executor=executor)

        store.add(EventRule(
            name="test",
            event_type="tool.executed",
            action="log",
            action_config={"message": "tool ran"},
        ))

        bus.emit(Event(type="tool.executed", data={"tool_name": "shell"}))
        await asyncio.sleep(0.05)

        executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_rule_filter_matching(self):
        """Rules with filters only fire when data matches."""
        store = EventRuleStore()
        executor = AsyncMock()
        bus = EventBus(store=store, action_executor=executor)

        store.add(EventRule(
            name="discord-only",
            event_type="message.received",
            filters={"channel": "discord"},
            action="log",
        ))

        # Non-matching event
        bus.emit(Event(type="message.received", data={"channel": "telegram"}))
        await asyncio.sleep(0.05)
        executor.execute.assert_not_called()

        # Matching event
        bus.emit(Event(type="message.received", data={"channel": "discord"}))
        await asyncio.sleep(0.05)
        executor.execute.assert_called_once()

    def test_recent_events(self):
        bus = EventBus()
        for i in range(5):
            bus.emit(Event(type=f"test.{i}"))

        recent = bus.recent_events(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0]["type"] == "test.4"

    def test_matches_filters_empty(self):
        event = Event(type="t", data={"a": 1})
        assert EventBus._matches_filters(event, {}) is True

    def test_matches_filters_match(self):
        event = Event(type="t", data={"channel": "discord", "x": 1})
        assert EventBus._matches_filters(event, {"channel": "discord"}) is True

    def test_matches_filters_no_match(self):
        event = Event(type="t", data={"channel": "slack"})
        assert EventBus._matches_filters(event, {"channel": "discord"}) is False


# --- ActionExecutor tests ---


class TestActionExecutor:
    """Tests for ActionExecutor."""

    @pytest.mark.asyncio
    async def test_log_action(self):
        executor = ActionExecutor()
        rule = EventRule(
            action=ActionType.LOG,
            action_config={"message": "something happened"},
        )
        event = Event(type="test")
        # Should not raise
        await executor.execute(rule, event)

    @pytest.mark.asyncio
    async def test_run_agent_action(self):
        agent_runner = AsyncMock()
        agent_runner.run.return_value = MagicMock(content="response")

        executor = ActionExecutor(agent_runner=agent_runner)
        rule = EventRule(
            action=ActionType.RUN_AGENT,
            action_config={
                "conversation_id": "test-conv-123",
                "message": "Alert: {tool_name} was executed",
            },
        )
        event = Event(type="tool.executed", data={"tool_name": "shell"})
        await executor.execute(rule, event)

        agent_runner.run.assert_called_once_with(
            conversation_id="test-conv-123",
            user_message="Alert: shell was executed",
        )

    @pytest.mark.asyncio
    async def test_execute_tool_action(self):
        tool_registry = AsyncMock()
        tool_registry.execute.return_value = MagicMock(success=True)

        executor = ActionExecutor(tool_registry=tool_registry)
        rule = EventRule(
            action=ActionType.EXECUTE_TOOL,
            action_config={"tool_name": "web_search", "args": {"query": "test"}},
        )
        event = Event(type="test")
        await executor.execute(rule, event)

        tool_registry.execute.assert_called_once_with("web_search", query="test")

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        executor = ActionExecutor()
        rule = EventRule(action="nonexistent")
        event = Event(type="test")
        # Should not raise
        await executor.execute(rule, event)

    @pytest.mark.asyncio
    async def test_missing_runner(self):
        executor = ActionExecutor(agent_runner=None)
        rule = EventRule(
            action=ActionType.RUN_AGENT,
            action_config={"conversation_id": "x", "message": "y"},
        )
        event = Event(type="test")
        # Should not raise
        await executor.execute(rule, event)
