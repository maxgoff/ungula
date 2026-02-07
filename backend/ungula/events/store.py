"""
In-memory event rule store.

Mirrors the CronStore pattern for CRUD on event rules.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .types import EventRule

logger = logging.getLogger(__name__)


class EventRuleStore:
    """In-memory store for event rules."""

    def __init__(self):
        self._rules: dict[str, EventRule] = {}

    def add(self, rule: EventRule) -> EventRule:
        """Add an event rule."""
        if not rule.id:
            rule.id = str(uuid4())[:8]
        self._rules[rule.id] = rule
        return rule

    def get(self, rule_id: str) -> EventRule | None:
        """Get a rule by ID."""
        return self._rules.get(rule_id)

    def list_all(self, enabled_only: bool = False) -> list[EventRule]:
        """List all rules."""
        rules = list(self._rules.values())
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        return rules

    def list_by_event_type(self, event_type: str) -> list[EventRule]:
        """List enabled rules matching a specific event type."""
        return [
            r for r in self._rules.values()
            if r.enabled and r.event_type == event_type
        ]

    def update(self, rule_id: str, **kwargs: Any) -> EventRule | None:
        """Update a rule's fields."""
        rule = self._rules.get(rule_id)
        if not rule:
            return None
        for key, value in kwargs.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        return rule

    def delete(self, rule_id: str) -> bool:
        """Delete a rule."""
        return self._rules.pop(rule_id, None) is not None

    def mark_fired(self, rule_id: str) -> None:
        """Record that a rule was fired."""
        rule = self._rules.get(rule_id)
        if rule:
            rule.fire_count += 1
            rule.last_fired = datetime.now(UTC)
