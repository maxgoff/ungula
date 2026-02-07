"""
Event Bus.

Lightweight pub/sub event bus with rule-based dispatch.
"""

import asyncio
import logging
from collections import deque
from typing import Any, Awaitable, Callable

from .store import EventRuleStore
from .types import Event

logger = logging.getLogger(__name__)

# Type for event handlers
EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """
    Pub/sub event bus with rule-based dispatch.

    Supports:
    - Programmatic subscribe(event_type, handler) for internal use
    - Rule-based dispatch via EventRuleStore + ActionExecutor
    - Rolling event log (last 100 events)
    """

    def __init__(
        self,
        store: EventRuleStore | None = None,
        action_executor: Any = None,
        max_log: int = 100,
    ):
        self.store = store or EventRuleStore()
        self.action_executor = action_executor
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._event_log: deque[dict[str, Any]] = deque(maxlen=max_log)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a programmatic handler for an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def emit(self, event: Event) -> None:
        """
        Emit an event. Dispatches to subscribers and matching rules.

        Uses fire-and-forget via asyncio.create_task.
        """
        # Log the event
        self._event_log.append({
            "id": event.id,
            "type": event.type,
            "data": event.data,
            "timestamp": event.timestamp.isoformat(),
        })

        # Dispatch to programmatic subscribers
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            asyncio.create_task(self._safe_call(handler, event))

        # Dispatch to matching rules
        rules = self.store.list_by_event_type(event.type)
        for rule in rules:
            if self._matches_filters(event, rule.filters):
                self.store.mark_fired(rule.id)
                if self.action_executor:
                    asyncio.create_task(
                        self._safe_execute_action(rule, event)
                    )

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent events from the log."""
        events = list(self._event_log)
        events.reverse()
        return events[:limit]

    @staticmethod
    def _matches_filters(event: Event, filters: dict[str, Any]) -> bool:
        """Check if event data matches all filter key-value pairs."""
        if not filters:
            return True
        for key, value in filters.items():
            if event.data.get(key) != value:
                return False
        return True

    @staticmethod
    async def _safe_call(handler: EventHandler, event: Event) -> None:
        """Call a handler, catching exceptions."""
        try:
            await handler(event)
        except Exception as e:
            logger.error("Event handler error for %s: %s", event.type, e)

    async def _safe_execute_action(self, rule, event: Event) -> None:
        """Execute a rule's action, catching exceptions."""
        try:
            await self.action_executor.execute(rule, event)
        except Exception as e:
            logger.error(
                "Action execution error for rule %s on %s: %s",
                rule.id, event.type, e,
            )
