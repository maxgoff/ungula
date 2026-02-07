"""
Event bus API routes.

CRUD for event rules plus event type listing and recent events.
"""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...events.types import ActionType, EventRule, EventType
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateRuleRequest(BaseModel):
    """Request to create an event rule."""

    name: str = Field(..., max_length=200)
    event_type: str = Field(..., max_length=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    action: str = Field(..., max_length=50)
    action_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class UpdateRuleRequest(BaseModel):
    """Request to update an event rule."""

    name: str | None = None
    event_type: str | None = None
    filters: dict[str, Any] | None = None
    action: str | None = None
    action_config: dict[str, Any] | None = None
    enabled: bool | None = None


def _get_event_bus(request: Request):
    """Get the event bus from app state."""
    bus = getattr(request.app.state, "event_bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="Event bus not initialized")
    return bus


def _rule_to_dict(rule: EventRule) -> dict[str, Any]:
    """Serialize an EventRule to a dict."""
    return {
        "id": rule.id,
        "name": rule.name,
        "event_type": rule.event_type,
        "filters": rule.filters,
        "action": rule.action,
        "action_config": rule.action_config,
        "enabled": rule.enabled,
        "fire_count": rule.fire_count,
        "last_fired": rule.last_fired.isoformat() if rule.last_fired else None,
    }


@router.get("/rules")
async def list_rules(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all event rules."""
    bus = _get_event_bus(request)
    rules = bus.store.list_all()
    return {
        "rules": [_rule_to_dict(r) for r in rules],
        "count": len(rules),
    }


@router.post("/rules")
async def create_rule(
    body: CreateRuleRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new event rule."""
    bus = _get_event_bus(request)

    rule = EventRule(
        id=str(uuid4())[:8],
        name=body.name,
        event_type=body.event_type,
        filters=body.filters,
        action=body.action,
        action_config=body.action_config,
        enabled=body.enabled,
    )

    bus.store.add(rule)
    return _rule_to_dict(rule)


@router.get("/rules/{rule_id}")
async def get_rule(
    rule_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get an event rule by ID."""
    bus = _get_event_bus(request)
    rule = bus.store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _rule_to_dict(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    body: UpdateRuleRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update an event rule."""
    bus = _get_event_bus(request)
    rule = bus.store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    updates = body.model_dump(exclude_none=True)
    updated = bus.store.update(rule_id, **updates)
    return _rule_to_dict(updated) if updated else {}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete an event rule."""
    bus = _get_event_bus(request)
    if not bus.store.delete(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted"}


@router.get("/types")
async def list_event_types(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List available event types and action types."""
    return {
        "event_types": [e.value for e in EventType],
        "action_types": [a.value for a in ActionType],
    }


@router.get("/recent")
async def recent_events(
    request: Request,
    limit: int = 50,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get recent events from the event log."""
    bus = _get_event_bus(request)
    events = bus.recent_events(limit=min(limit, 100))
    return {
        "events": events,
        "count": len(events),
    }
